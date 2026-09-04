#!/usr/bin/env python
"""Crea la primera cuenta root del panel de administración.

Uso:
    python scripts/create_root.py --username admin --display-name "Nombre Apellido"

Pide la contraseña de forma interactiva (no queda en el historial de la
terminal). Sin este script no hay forma de entrar al panel la primera vez:
no existe registro ni alta automática de cuentas -- el root gestiona todas
las demás cuentas (dependencias, admin general) desde su propio panel una
vez que existe.
"""
import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services import admin_service  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Crea una cuenta root para el panel de administración.")
    parser.add_argument("--username", required=True)
    parser.add_argument("--display-name", required=True)
    args = parser.parse_args()

    password = getpass.getpass("Contraseña para la cuenta root: ")
    confirm = getpass.getpass("Confirma la contraseña: ")
    if password != confirm:
        print("Las contraseñas no coinciden.")
        sys.exit(1)
    if len(password) < 8:
        print("La contraseña debe tener al menos 8 caracteres.")
        sys.exit(1)

    try:
        admin_id = admin_service.create_admin(args.username, password, args.display_name, "root")
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    print(f"Cuenta root creada (id={admin_id}, usuario={args.username}). Ya puedes iniciar sesión en /root.")


if __name__ == "__main__":
    main()
