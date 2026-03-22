# Web UI Libraries
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from contextlib import asynccontextmanager
import requests
import xml.etree.ElementTree as ET

# MCP libraries
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# LangChain Libraries
from langchain_mcp_adapters.tools import load_mcp_tools
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

# Set Local MCP Logging
from utilities.logging_config import setup_logging
logger = setup_logging("dashboard_app.log")

# Load System Prompt and Message Formatter
from utilities.prompt import AGENT_SYSTEM_PROMPT
from utilities.chat import format_agent_response

# Load Environment and set MCP Filepath
import os
from dotenv import load_dotenv
load_dotenv()

### Override existing MCP Location and Toolset to import custom tools from:
# https://github.com/wjsutton/tableau-mcp-experimental for dashboard extension
# Remember to execute 'npm install' & 'npm run build' in the tableau-mcp-experimental folder
# These tools are fixed to 1 datasource via the FIXED_DATASOURCE_LUID environment variable in your .env file
TABLEAU_SERVER = os.environ.get("SERVER")
SITE_NAME = os.environ.get("SITE_NAME")
PAT_NAME = os.environ.get("PAT_NAME")
PAT_VALUE = os.environ.get("PAT_VALUE")
TOKEN_CACHE = {
    "token": None,
    "site_id": None
}
DS_CACHE = {
}
def get_tableau_auth_token():
    #if TOKEN_CACHE["token"]:
    #    return TOKEN_CACHE["token"], TOKEN_CACHE["site_id"]

    url = f"{TABLEAU_SERVER}/api/3.19/auth/signin"

    payload = {
        "credentials": {
            "personalAccessTokenName": PAT_NAME,
            "personalAccessTokenSecret": PAT_VALUE,
            "site": {"contentUrl": SITE_NAME}
        }
    }

    response = requests.post(url, json=payload)
    print("🔍 STATUS:", response.status_code)
    print("🔍 RESPONSE TEXT:", response.text)

    if response.status_code != 200:
        raise Exception(f"Auth failed: {response.status_code} - {response.text}")
    #data = response.json()
    root = ET.fromstring(response.text)
    # Namespace handling
    ns = {"t": "http://tableau.com/api"}
    credentials = root.find("t:credentials", ns)
    token = credentials.attrib["token"]
    site_id = credentials.find("t:site", ns).attrib["id"]
    print("🔍 TOKEN:", token)
    print("🔍 SITE_ID:", site_id)
    TOKEN_CACHE["token"] = token
    TOKEN_CACHE["site_id"] = site_id

    return TOKEN_CACHE["token"], TOKEN_CACHE["site_id"]

mcp_location = 'C:/Users/sanchita.jain/tableau_mcp/tableau-mcp-pinned/build/index.js'
tool_list = 'list-fields, read-metadata, query-datasource, get-dashboard-filtered-datasources'
datasource_luid = os.environ.get('FIXED_DATASOURCE_LUID')

custom_env = {
    "INCLUDE_TOOLS": tool_list
    }

# Set Langfuse Tracing
from langfuse.langchain import CallbackHandler
langfuse_handler = CallbackHandler()

# Global variables for agent and session
agent = None
session_context = None

# Global async context manager for MCP connection
@asynccontextmanager
async def lifespan(app: FastAPI):
    global agent
    logger.info("Starting up application...")
    
    try:
        # Setup MCP connection
        server_params = StdioServerParameters(
            command="node",
            args=[mcp_location],
            env=custom_env
        )

        # Use proper async context management
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as client_session:
                # Initialize the connection
                await client_session.initialize()

                # Get tools, filter tools using the .env config
                mcp_tools = await load_mcp_tools(client_session)
                
                # Set AI Model
                llm = ChatOpenAI(model="gpt-4o", temperature=0)

                # Create the agent
                checkpointer = InMemorySaver()
                agent = create_react_agent(model=llm, tools=mcp_tools, prompt=AGENT_SYSTEM_PROMPT, checkpointer=checkpointer)
                
                yield
        
    # Error Handling
    except Exception as e:
        logger.error(f"Failed to initialize agent: {e}")
        raise

# Create FastAPI app with lifespan
app = FastAPI(
    title="Tableau AI Chat", 
    description="Simple AI chat interface for Tableau data",
    lifespan=lifespan
)

# Serve static files (HTML, CSS, JS)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Request/Response models
class ChatRequest(BaseModel):
    message: str
    dashboardName: str
    worksheetName: str | None = None
    datasources: list[str]

class ChatResponse(BaseModel):
    response: str

def map_datasource_names_to_luids(names: list[str]) -> list[dict]:
    deff = []
    foundAll = 1
    for name in names:
        if(name in DS_CACHE):
            deff.append({
                    "name": name,
                    "luid": DS_CACHE[name]
                })
        else:
            foundAll = 0
            break
    if(foundAll):
        return deff

    token, site_id = get_tableau_auth_token()

    url = f"{TABLEAU_SERVER}/api/metadata/graphql"

    headers = {
        "X-Tableau-Auth": token,
        "Content-Type": "application/json"
    }

    query = """
    query {
      publishedDatasources {
        luid
        name
      }
    }
    """

    response = requests.post(url, json={"query": query}, headers=headers)
    print("🔍 STATUS:", response.status_code)
    print("🔍 RESPONSE TEXT:", response.text[:500])


    if response.status_code != 200:
        raise Exception(f"GraphQL failed: {response.text}")

    data = response.json().get("data", {})

    published = data.get("publishedDatasources", [])

    all_ds = published
    print("🔍 ALL_DS:", all_ds)
    matched = []
    seen = set()

    for frontend_name in names:
        if not frontend_name:
            continue
        for ds in all_ds:
            ds_name = ds.get("name")
            # 🔥 Skip invalid values
            if not ds_name:
                continue
            if (
                frontend_name.lower() in ds_name.lower()
                and ds["luid"] not in seen
            ):
                matched.append({
                    "name": ds_name,
                    "luid": ds["luid"]
                })
                seen.add(ds["luid"])
                DS_CACHE[ds_name] = ds["luid"]
    return matched

@app.get("/")
def home():
    """Serve the main HTML page"""
    return FileResponse('static/index.html')

@app.get("/index.html")
def static_index():
    return FileResponse('static/index.html')

@app.post("/chat")
async def chat(request: Request):
    """Handle chat messages - this is where the AI magic happens"""
    print('cAME HERE1')
    print(request)
    body = await request.json()
    print("🔥 RAW REQUEST:", body)
    global agent
    
    if agent is None:
        logger.error("Agent not initialized")
        raise HTTPException(status_code=500, detail="Agent not initialized. Please restart the server.")
    
    try:      
        # Create proper message format for LangGraph
        datasource_luids = map_datasource_names_to_luids(body.get('datasources', []))
        luid_list = [ds["luid"] for ds in datasource_luids]
        print('datasources_luids:')
        print(datasource_luids)

        print('DS_CACHE:')
        print(DS_CACHE)
        print(body.get('message'))
        print('>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>')
        print(luid_list)
        print('dashboardName:')
        print(body.get('dashboardName'))
        print('message:')
        print(body.get('message'))
        print('>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>')
        context_text = f"""
        You are working with a Tableau dashboard.

        Dashboard: {body.get('dashboardName')}

        Allowed datasource LUIDs:
        {luid_list}

        IMPORTANT:
        - ALWAYS use one of these datasource LUIDs
        - NEVER use any other datasource
        - When calling query tool, ALWAYS include datasourceLuid
        """

        messages = [
            HumanMessage(
                content=context_text + "\n\nUser Question: " + body.get('message')
            )
        ]
        print('messages:')
        print(messages)
        print(request)
        
        # Get response from agent
        response_text = await format_agent_response(agent, messages, langfuse_handler)
        
        return ChatResponse(response=response_text)
        
    # Error Handling
    except Exception as e:
        print('cAME HERE2')
        print(e)
        #print(e.traceback)
        logger.error(f"Error processing chat request: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error processing request: {str(e)}")

# Run the app
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)