import os

from flask import Flask

# Repo root is one level up from this package (web/__init__.py -> repo root),
# same root that engines/ and common/ already live at.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def create_app():
    app = Flask(
        __name__,
        template_folder=os.path.join(_REPO_ROOT, "templates"),
        static_folder=os.path.join(_REPO_ROOT, "static"),
        static_url_path="/static",
    )
    app.config["JSON_SORT_KEYS"] = False

    from web.routes.generator import bp as generator_bp
    from web.routes.transformer_exct import bp as transformer_exct_bp
    from web.routes.transformer_gsut import bp as transformer_gsut_bp
    from web.routes.transformer_overall import bp as transformer_overall_bp
    from web.routes.transformer_aux import bp as transformer_aux_bp
    from web.routes.motor_idfan import bp as motor_idfan_bp
    from web.routes.motor_pa_fan import bp as motor_pa_fan_bp
    from web.routes.motor_fd_fan import bp as motor_fd_fan_bp

    app.register_blueprint(generator_bp)
    app.register_blueprint(transformer_exct_bp)
    app.register_blueprint(transformer_gsut_bp)
    app.register_blueprint(transformer_overall_bp)
    app.register_blueprint(transformer_aux_bp)
    app.register_blueprint(motor_idfan_bp)
    app.register_blueprint(motor_pa_fan_bp)
    app.register_blueprint(motor_fd_fan_bp)

    @app.route("/")
    def index():
        # Phase 1 has no Home page yet — send straight to the one reference
        # page that exists so the root URL isn't a dead end during review.
        from flask import redirect, url_for
        return redirect(url_for("transformer_gsut.page"))

    return app
