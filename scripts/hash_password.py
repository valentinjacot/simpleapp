import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from auth import hash_password

if __name__ == "__main__":
    password = getpass.getpass("Password to hash: ")
    print(hash_password(password))
