import os

class Config:
    SQLALCHEMY_DATABASE_URI = "postgresql://postgres:password@localhost:5432/projectdb"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = "supersecretkey"