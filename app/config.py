import os


class Config:
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
    DEMO_RESET = False
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg://shop:shop@localhost:5434/shop",
    )


class DevelopmentConfig(Config):
    DEMO_RESET = True


class TestingConfig(Config):
    TESTING = True
    DEMO_RESET = False
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+psycopg://shop:shop@localhost:5433/shop_test",
    )


class ProductionConfig(Config):
    DEMO_RESET = False
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL")


CONFIGS = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}
