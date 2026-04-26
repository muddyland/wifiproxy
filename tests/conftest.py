import pytest
from app import create_app, db as _db
from app.models import User, WifiNetwork, DhcpConfig, TailscaleConfig
from config import Config


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SECRET_KEY = "test-secret-key-not-for-production"
    WTF_CSRF_ENABLED = False
    SESSION_COOKIE_SECURE = False
    RATELIMIT_ENABLED = False
    WIFI_WATCHDOG = False
    WAN_INTERFACE = "wlan0"
    LAN_INTERFACE = "eth0"
    NM_LAN_CONNECTION = "Ethernet-Share"
    DNSMASQ_CONF = "/tmp/test_dnsmasq.conf"
    DNSMASQ_LEASES = "/tmp/test_dnsmasq.leases"


@pytest.fixture()
def app():
    application = create_app(TestConfig)
    with application.app_context():
        _db.create_all()
        yield application
        _db.session.remove()
        _db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def auth_client(app, client):
    """A test client that is already logged in as admin."""
    with app.app_context():
        user = User.query.filter_by(username="admin").first()
        if not user:
            user = User(username="admin")
            user.set_password("admin")
            _db.session.add(user)
            _db.session.commit()

    client.post("/login", data={"username": "admin", "password": "admin"})
    return client


@pytest.fixture()
def sample_network(app):
    with app.app_context():
        net = WifiNetwork(ssid="TestNetwork", priority=10)
        net.password = "testpass123"
        _db.session.add(net)
        _db.session.commit()
        yield net
