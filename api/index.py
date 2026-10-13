import sys
import os

# Ensure the project root directory is in Python's module search path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
