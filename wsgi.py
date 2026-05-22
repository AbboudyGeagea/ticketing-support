from app import create_app
from app.celery_app import celery, make_celery

app = create_app()
make_celery(app)  # binds the module-level celery instance to the Flask app

if __name__ == "__main__":
    app.run()
