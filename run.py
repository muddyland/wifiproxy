import os
from app import create_app

app = create_app()

if __name__ == "__main__":
    # Bind only to the LAN interface (eth0 = 192.168.50.1) so the management
    # UI is never reachable from the upstream WiFi network (wlan0).
    host = os.environ.get("BIND_HOST", "192.168.50.1")
    port = int(os.environ.get("PORT", 80))
    app.run(host=host, port=port, debug=False)
