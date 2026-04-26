from flask import Flask, redirect, url_for, request, g
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from config import Config

db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address, default_limits=[])


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Harden session cookies
    app.config.setdefault("SESSION_COOKIE_HTTPONLY", True)
    app.config.setdefault("SESSION_COOKIE_SAMESITE", "Lax")
    # Set SECURE only when not in dev/testing (caller can override)
    app.config.setdefault("SESSION_COOKIE_SECURE", not app.debug)

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)

    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please log in to continue."
    login_manager.login_message_category = "warning"

    from app.auth import bp as auth_bp
    from app.wifi import bp as wifi_bp
    from app.dhcp import bp as dhcp_bp
    from app.tailscale import bp as tailscale_bp
    from app.system import bp as system_bp
    from app.main import bp as main_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(wifi_bp, url_prefix="/wifi")
    app.register_blueprint(dhcp_bp, url_prefix="/dhcp")
    app.register_blueprint(tailscale_bp, url_prefix="/tailscale")
    app.register_blueprint(system_bp, url_prefix="/system")

    @app.after_request
    def set_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=()"
        # Only allow resources from self + CDNs we actually use
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' "
            "  https://cdn.jsdelivr.net https://unpkg.com; "
            "style-src 'self' 'unsafe-inline' "
            "  https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
            "font-src 'self' https://cdnjs.cloudflare.com; "
            "img-src 'self' data:; "
            "connect-src 'self';"
        )
        # Don't advertise server info
        response.headers.pop("Server", None)
        return response

    with app.app_context():
        db.create_all()
        _seed_defaults()

    return app


def _seed_defaults():
    from app.models import User, DhcpConfig, TailscaleConfig

    if not User.query.first():
        admin = User(username="admin")
        admin.set_password("admin")
        db.session.add(admin)

    if not DhcpConfig.query.first():
        db.session.add(DhcpConfig())

    if not TailscaleConfig.query.first():
        db.session.add(TailscaleConfig())

    db.session.commit()
