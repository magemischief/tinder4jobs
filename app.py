from __future__ import annotations

from flask import Flask, redirect, render_template, url_for

from api.routes import api
from database import init_db

init_db()


def create_app() -> Flask:
    app = Flask(__name__)
    app.register_blueprint(api)

    @app.get("/")
    def index():
        return redirect(url_for("swipe_page"))

    @app.get("/review")
    def swipe_page():
        return render_template("swipe.html", active_page="swipe")

    @app.get("/applications")
    def applications_page():
        return render_template("applications.html", active_page="applications")

    @app.get("/notifications")
    def notifications_page():
        return render_template("notifications.html", active_page="notifications")

    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=True, port=5000)