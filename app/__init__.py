import os

from flask import Flask, jsonify, send_from_directory
from werkzeug.exceptions import HTTPException

from app.api import api_bp
from app.config import CONFIGS
from app.errors import AppError
from app.extensions import db
from app.services.provider import MockPaymentProvider

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), os.pardir, "frontend")


def create_app(config_name: str | None = None) -> Flask:
    name = config_name or os.environ.get("APP_ENV", "development")
    app = Flask(__name__, static_folder=os.path.abspath(FRONTEND_DIR), static_url_path="/static")
    app.config.from_object(CONFIGS[name])
    app.json.sort_keys = False
    app.config.setdefault("PAYMENT_PROVIDER", MockPaymentProvider())

    db.init_app(app)
    app.register_blueprint(api_bp, url_prefix="/api")
    _register_error_handlers(app)

    @app.get("/")
    def checkout_page():
        return send_from_directory(app.static_folder, "index.html")

    return app


def _register_error_handlers(app: Flask) -> None:
    @app.errorhandler(AppError)
    def handle_app_error(error: AppError):
        db.session.rollback()
        return jsonify(error={"code": error.code, "message": error.message}), error.status

    @app.errorhandler(HTTPException)
    def handle_http(error: HTTPException):
        return jsonify(error={"code": error.name.lower().replace(" ", "_"), "message": error.description}), error.code

    @app.errorhandler(Exception)
    def handle_unexpected(error: Exception):
        if isinstance(error, HTTPException):
            return handle_http(error)
        app.logger.exception("Unhandled error")
        db.session.rollback()
        return jsonify(
            error={
                "code": "internal_error",
                "message": "Something went wrong while handling the request.",
            }
        ), 500
