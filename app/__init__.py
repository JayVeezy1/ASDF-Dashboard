import logging
import logging.config
import os
from distutils.util import strtobool

from dotenv import load_dotenv
from flask import Flask
from werkzeug.exceptions import NotFound
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.middleware.dispatcher import DispatcherMiddleware

from frontend.app.auth import login_mngr
from frontend.app.blueprints.auth import auth as auth_blueprint
from frontend.app.blueprints.dashboard import dashboard as dashboard_blueprint
from frontend.app.blueprints.main import main as main_blueprint
from frontend.app.blueprints.task import task as task_blueprint
from frontend.app.cache import cache
from frontend.app.conf.config import ProductionConfig, DevConfig
from frontend.app.db import db
from frontend.app.mail import mail
from frontend.app.util import ensure_exists_folder
from frontend.app.celery_app import celery_app


def setup_logging(app_root):
    ensure_exists_folder(os.path.join(app_root, "log"))
    log_conf_path = os.path.join(app_root, "conf", "logging.conf")
    log_file_path = os.path.join(app_root, "log", "demo.log")

    logging.config.fileConfig(log_conf_path, defaults={'logfilename': log_file_path}, disable_existing_loggers=False)


def register_extensions(app):
    db.init_app(app)
    # toolbar.init_app(app)
    login_mngr.init_app(app)
    mail.init_app(app)
    cache.init_app(app)


def register_blueprints(app):
    app.register_blueprint(main_blueprint)
    app.register_blueprint(auth_blueprint)
    app.register_blueprint(dashboard_blueprint)
    app.register_blueprint(task_blueprint)


def setup_db(app):
    if bool(strtobool(os.getenv("DATABASE_DROP_ALL", 'false'))):
        with app.app_context():
            db.drop_all()       # removed app=app

    with app.app_context():
        db.create_all()  # create db         # removed app=app
    app.logger.debug("Setup db")


def create_app(configuration=ProductionConfig()):
    load_dotenv()
    app_root = os.path.dirname(os.path.realpath(__file__))  # App root folder

    # Configure logging
    setup_logging(app_root)

    # Flask
    instance_path = os.path.join(os.path.dirname(app_root), 'instance')
    app = Flask(__name__, instance_path=instance_path)

    # ProxyFix
    if isinstance(configuration, ProductionConfig):
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1, x_port=1)

    # Dispatcher middleware (debug)
    if isinstance(configuration, DevConfig):
        if configuration.APP_URL_PREFIX and configuration.APP_URL_PREFIX != '':
            app.wsgi_app = DispatcherMiddleware(NotFound(),
                                                {configuration.APP_URL_PREFIX: app.wsgi_app})

    # Config
    app.config.from_object(configuration)
    if isinstance(configuration, DevConfig):
        app.config.update(
            SQLALCHEMY_DATABASE_URI='sqlite:///' + os.path.join(app.instance_path, 'test.sqlite'),
            UPLOAD_FOLDER=os.path.join(app.instance_path, 'upload'),
        )
    elif isinstance(configuration, ProductionConfig):
        app.config.update(
            SQLALCHEMY_DATABASE_URI=f'postgresql://{os.getenv("POSTGRES_USER")}:{os.getenv("POSTGRES_PASSWORD")}'
                                    f'@postgres:5432/{os.getenv("POSTGRES_DB")}',
            UPLOAD_FOLDER=os.path.join(app.instance_path, 'upload'),
        )

    # ensure instance/upload folders exists
    ensure_exists_folder(app.instance_path)
    ensure_exists_folder(app.config['UPLOAD_FOLDER'])

    # Debug mode
    app.debug = True
    log = app.logger

    # Register extensions, blueprints
    register_extensions(app)
    log.debug('Registered extensions')

    register_blueprints(app)
    log.debug('Registered blueprints')

    # Setup database
    setup_db(app)

    # Celery
    celery_app.conf.update(app.config)
    log.debug('Created app')
    print(f"{app.config}")

    return app


def start_app_from_main(use_this_function: False):
    if use_this_function:
        app = create_app(configuration=DevConfig())
        app.run(debug=True)
    return None


if __name__ == '__main__':
    app = create_app(configuration=DevConfig())
    app.run(debug=True)

