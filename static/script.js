console.log("🔥 FINAL VERSION LOADED");

let dashboardNameForMCP = null;
let worksheetNameForMCP = null;
let datasourceNamesForMCP = [];

document.addEventListener("DOMContentLoaded", async () => {
    try {
        await tableau.extensions.initializeAsync();

        const dashboard = tableau.extensions.dashboardContent.dashboard;

        dashboardNameForMCP = dashboard.name;

        console.log("✅ Dashboard:", dashboardNameForMCP);

        const worksheets = dashboard.worksheets;

        if (!worksheets || worksheets.length === 0) {
            console.error("❌ No worksheets found in dashboard");
            return;
        }

        let allDatasourceNames = new Set();
        for (const ws of worksheets) {
            const dsList = await ws.getDataSourcesAsync();
            dsList.forEach(ds => allDatasourceNames.add(ds.name));
        }
        datasourceNamesForMCP = Array.from(allDatasourceNames);
        console.log("🔥 Filtered Datasource Names:", datasourceNamesForMCP);
    } catch (error) {
        console.error("❌ Error initializing Tableau Extension:", error);
    }
});

async function sendMessage() {
    try {
        console.log("📤 Sending Data:");
        console.log("Dashboard:", dashboardNameForMCP);
        console.log("Worksheet:", worksheetNameForMCP);
        console.log("Datasources:", datasourceNamesForMCP);

        const input = document.getElementById('messageInput');
        const message = input.value.trim();

        if (!message) return;

        // UI update
        addMessage(message, 'user');
        input.value = '';

        const btn = document.getElementById('sendBtn');
        btn.disabled = true;
        btn.textContent = 'Thinking...';

        // 🔥 SEND EVERYTHING TO BACKEND
        const response = await fetch('/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: message,
                dashboardName: dashboardNameForMCP,
                worksheetName: worksheetNameForMCP,
                datasources: datasourceNamesForMCP   // ✅ KEY OUTPUT
            })
        });

        const data = await response.json();

        if (response.ok) {
            addMessage(data.response, 'bot');
        } else {
            addMessage('Sorry, something went wrong!', 'bot');
        }

        btn.disabled = false;
        btn.textContent = 'Send';

    } catch (error) {
        console.error('❌ Error:', error);
        addMessage('Error occurred while sending message.', 'bot');
    }
}

function addMessage(text, type) {
    const chatBox = document.getElementById('chatBox');
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${type}`;
    messageDiv.innerHTML = text.replace(/\n/g, '<br>');
    chatBox.appendChild(messageDiv);

    chatBox.scrollTop = chatBox.scrollHeight;
}

function handleEnter(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        sendMessage();
    }
}

// Focus input on load
document.addEventListener('DOMContentLoaded', function () {
    document.getElementById('messageInput').focus();
});