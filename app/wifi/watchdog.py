"""Background thread: connect to the highest-priority visible WiFi network."""
import threading
import time
import logging

logger = logging.getLogger(__name__)


def start(app):
    """Start the watchdog — no-op when WIFI_WATCHDOG config is False."""
    if not app.config.get("WIFI_WATCHDOG", True):
        return
    t = threading.Thread(target=_loop, args=(app,), daemon=True)
    t.start()
    app.logger.info("WiFi priority watchdog started (interval: 60s).")


def _loop(app):
    while True:
        time.sleep(60)
        try:
            with app.app_context():
                _check(app)
        except Exception as exc:
            logger.error("Watchdog error: %s", exc)


def _check(app):
    from app.models import WifiNetwork
    from app.wifi import utils

    current = utils.get_current_connection()
    if not current["connected"]:
        return

    current_net = WifiNetwork.query.filter_by(ssid=current["ssid"]).first()
    current_priority = current_net.priority if current_net else 0

    candidates = (
        WifiNetwork.query
        .filter(
            WifiNetwork.priority > current_priority,
            WifiNetwork.auto_connect.is_(True),
        )
        .order_by(WifiNetwork.priority.desc())
        .all()
    )
    if not candidates:
        return

    visible = {n["ssid"] for n in utils.scan_networks(rescan=False)}
    for net in candidates:
        if net.ssid in visible:
            app.logger.info("Watchdog: upgrading to '%s' (priority %s)", net.ssid, net.priority)
            ok, msg = utils.connect(net.ssid, net.password, net.bssid)
            if ok:
                app.logger.info("Watchdog: connected to '%s'", net.ssid)
            else:
                app.logger.warning("Watchdog: failed to connect to '%s': %s", net.ssid, msg)
            return
