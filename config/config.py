import os
import sys
import logging
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.ERROR, format='%(levelname)s: %(message)s')

# Project level .env file path
env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')

if not os.path.exists(env_path):
    logging.error("The .env file does not exist at the project level.")
    sys.exit(1)

load_dotenv(dotenv_path=env_path)

REQUIRED_ENV_VARS = [
    "VAULT_HOSTNAME",
    "VAULT_USERNAME",
    "VAULT_PASSWORD",
    "GEMINI_API_KEY"
]

# Check for missing or empty environment variables
for var in REQUIRED_ENV_VARS:
    value = os.getenv(var)
    if not value or not value.strip():
        logging.error(f"Environment variable '{var}' is missing or empty in the .env file.")
        sys.exit(1)

# Export variables for application use
VAULT_HOSTNAME = os.getenv("VAULT_HOSTNAME")
VAULT_USERNAME = os.getenv("VAULT_USERNAME")
VAULT_PASSWORD = os.getenv("VAULT_PASSWORD")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
