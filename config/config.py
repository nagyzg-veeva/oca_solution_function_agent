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

USE_CSV_INPUT = os.getenv("USE_CSV_INPUT", "false").lower() in ("true", "1", "yes")

# Check for GEMINI_API_KEY
gemini_key = os.getenv("GEMINI_API_KEY")
if not gemini_key or not gemini_key.strip():
    logging.error("Environment variable 'GEMINI_API_KEY' is missing or empty in the .env file.")
    sys.exit(1)

# Check for Vault variables if not explicitly running in CSV input mode
vault_vars = ["VAULT_HOSTNAME", "VAULT_USERNAME", "VAULT_PASSWORD", "VAULT_ORG_NAME"]
missing_vault_vars = [v for v in vault_vars if not os.getenv(v) or not os.getenv(v).strip()]

if missing_vault_vars and not USE_CSV_INPUT:
    logging.warning(f"Vault environment variables missing {missing_vault_vars}. Falling back to USE_CSV_INPUT = True.")
    USE_CSV_INPUT = True

# Export variables for application use
VAULT_HOSTNAME = os.getenv("VAULT_HOSTNAME", "")
VAULT_USERNAME = os.getenv("VAULT_USERNAME", "")
VAULT_PASSWORD = os.getenv("VAULT_PASSWORD", "")
VAULT_ORG_NAME = os.getenv("VAULT_ORG_NAME", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

