#!/usr/bin/env bash
# Arranca backend (FastAPI) y frontend (Vite) en paralelo.
#
# Uso:
#   ./dev.sh
#   BOOTSTRAP_ONLY=1 ./dev.sh
#   SKIP_BOOTSTRAP=1 ./dev.sh
#
# El bootstrap es idempotente. Crea backend/.venv, instala dependencias
# Python/Node y prepara las librerías nativas que no caben en un virtualenv
# (Pango/ODBC). En una máquina nueva puede pedir contraseña de administrador.

set -Eeuo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$ROOT/backend"
FRONTEND_DIR="$ROOT/frontend"
VENV_DIR="$BACKEND_DIR/.venv"
PID_BACK=""
PID_FRONT=""
export BACKEND_PORT="${BACKEND_PORT:-8000}"
export FRONTEND_PORT="${FRONTEND_PORT:-5173}"
export CORS_ORIGINS="${CORS_ORIGINS:-[\"http://localhost:$FRONTEND_PORT\",\"http://127.0.0.1:$FRONTEND_PORT\"]}"

RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[0;33m'
NC='\033[0m'

cleanup() {
  if [ -z "$PID_BACK" ] && [ -z "$PID_FRONT" ]; then
    return
  fi
  echo ""
  echo -e "${CYAN}Parando servicios...${NC}"
  [ -z "$PID_BACK" ] || kill "$PID_BACK" 2>/dev/null || true
  [ -z "$PID_FRONT" ] || kill "$PID_FRONT" 2>/dev/null || true
  [ -z "$PID_BACK" ] || wait "$PID_BACK" 2>/dev/null || true
  [ -z "$PID_FRONT" ] || wait "$PID_FRONT" 2>/dev/null || true
  PID_BACK=""
  PID_FRONT=""
  echo -e "${GREEN}Servicios parados.${NC}"
}
trap cleanup EXIT INT TERM

log() {
  local color="$1"
  shift
  echo -e "${color}[bootstrap]${NC} $*"
}

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

python_is_supported() {
  "$1" -c 'import sys; raise SystemExit(sys.version_info < (3, 11))' >/dev/null 2>&1
}

node_is_supported() {
  command_exists node && [ "$(node -p 'Number(process.versions.node.split(".")[0])')" -ge 18 ]
}

find_python() {
  local candidate
  for candidate in python3.13 python3.12 python3.11 python3; do
    if command_exists "$candidate" && python_is_supported "$candidate"; then
      command -v "$candidate"
      return
    fi
  done
  return 1
}

ensure_homebrew() {
  if command_exists brew; then
    return
  fi
  log "$YELLOW" "Homebrew no está instalado. Instalándolo..."
  if ! command_exists curl; then
    echo -e "${RED}Se necesita curl para instalar Homebrew.${NC}" >&2
    exit 1
  fi
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  if [ -x /opt/homebrew/bin/brew ]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
  elif [ -x /usr/local/bin/brew ]; then
    eval "$(/usr/local/bin/brew shellenv)"
  fi
}

brew_install_if_missing() {
  local package="$1"
  if ! brew list --versions "$package" >/dev/null 2>&1; then
    log "$YELLOW" "Instalando $package..."
    brew install "$package"
  fi
}

ensure_macos_dependencies() {
  ensure_homebrew
  brew_install_if_missing python@3.13
  brew_install_if_missing node
  brew_install_if_missing azure-cli
  brew_install_if_missing unixodbc
  brew_install_if_missing pango

  if ! odbcinst -q -d 2>/dev/null | grep -q "ODBC Driver 18 for SQL Server"; then
    log "$YELLOW" "Instalando ODBC Driver 18 for SQL Server..."
    brew tap microsoft/mssql-release https://github.com/microsoft/homebrew-mssql-release
    HOMEBREW_ACCEPT_EULA=Y brew install msodbcsql18
  fi
}

ensure_debian_dependencies() {
  local sudo_cmd=()
  if [ "$(id -u)" -ne 0 ]; then
    if ! command_exists sudo; then
      echo -e "${RED}Se necesita sudo para instalar dependencias del sistema.${NC}" >&2
      exit 1
    fi
    sudo_cmd=(sudo)
  fi

  log "$YELLOW" "Instalando dependencias del sistema con apt..."
  "${sudo_cmd[@]}" apt-get update
  "${sudo_cmd[@]}" apt-get install -y \
    ca-certificates curl gnupg git \
    python3 python3-venv python3-pip \
    nodejs npm \
    unixodbc unixodbc-dev \
    libpango-1.0-0 libpangoft2-1.0-0 libcairo2 \
    libgdk-pixbuf-2.0-0 libffi-dev shared-mime-info

  if ! node_is_supported; then
    log "$YELLOW" "La versión de Node es antigua. Instalando Node 20..."
    curl -fsSL https://deb.nodesource.com/setup_20.x -o /tmp/setup-node.sh
    "${sudo_cmd[@]}" bash /tmp/setup-node.sh
    "${sudo_cmd[@]}" apt-get install -y nodejs
  fi

  if ! command_exists az; then
    log "$YELLOW" "Instalando Azure CLI..."
    curl -sL https://aka.ms/InstallAzureCLIDeb -o /tmp/install-azure-cli.sh
    "${sudo_cmd[@]}" bash /tmp/install-azure-cli.sh
  fi

  if ! odbcinst -q -d 2>/dev/null | grep -q "ODBC Driver 18 for SQL Server"; then
    local distro version package_file
    distro="$(. /etc/os-release && echo "$ID")"
    version="$(. /etc/os-release && echo "$VERSION_ID")"
    package_file="/tmp/packages-microsoft-prod.deb"
    log "$YELLOW" "Instalando ODBC Driver 18 for SQL Server..."
    curl -fsSL "https://packages.microsoft.com/config/${distro}/${version}/packages-microsoft-prod.deb" \
      -o "$package_file"
    "${sudo_cmd[@]}" dpkg -i "$package_file"
    "${sudo_cmd[@]}" apt-get update
    "${sudo_cmd[@]}" env ACCEPT_EULA=Y apt-get install -y msodbcsql18
  fi
}

ensure_system_dependencies() {
  case "$(uname -s)" in
    Darwin)
      ensure_macos_dependencies
      ;;
    Linux)
      if command_exists apt-get; then
        ensure_debian_dependencies
      else
        echo -e "${RED}Distribución Linux no soportada automáticamente. Se requiere Python 3.11+, Node, Azure CLI, Pango y ODBC Driver 18.${NC}" >&2
        exit 1
      fi
      ;;
    *)
      echo -e "${RED}dev.sh soporta macOS y Linux Debian/Ubuntu. En Windows usa WSL2.${NC}" >&2
      exit 1
      ;;
  esac
}

ensure_azure_login() {
  if [ "${SKIP_AZURE_LOGIN:-0}" = "1" ]; then
    return
  fi
  if ! az account show >/dev/null 2>&1; then
    log "$YELLOW" "No hay sesión de Azure activa. Abriendo az login..."
    az login
  fi
}

bootstrap() {
  log "$CYAN" "Preparando entorno (SKIP_BOOTSTRAP=1 para saltar)..."

  if [ "${SKIP_SYSTEM_DEPS:-0}" != "1" ]; then
    ensure_system_dependencies
  fi

  if ! node_is_supported; then
    echo -e "${RED}Se requiere Node 18 o superior.${NC}" >&2
    exit 1
  fi

  local python_bin
  if ! python_bin="$(find_python)"; then
    echo -e "${RED}No se encontró Python 3.11 o superior.${NC}" >&2
    exit 1
  fi

  if [ ! -x "$VENV_DIR/bin/python" ] || ! python_is_supported "$VENV_DIR/bin/python"; then
    if [ -d "$VENV_DIR" ]; then
      echo -e "${RED}backend/.venv usa un Python incompatible. Elimínalo y vuelve a ejecutar ./dev.sh.${NC}" >&2
      exit 1
    fi
    log "$YELLOW" "Creando backend/.venv con $("$python_bin" --version)..."
    "$python_bin" -m venv "$VENV_DIR"
  fi

  local venv_python="$VENV_DIR/bin/python"
  local requirements="$BACKEND_DIR/requirements.txt"
  local requirements_dev="$BACKEND_DIR/requirements-dev.txt"
  local requirements_stamp="$VENV_DIR/.requirements.stamp"

  if [ ! -f "$requirements_stamp" ] \
    || [ "$requirements" -nt "$requirements_stamp" ] \
    || [ "$requirements_dev" -nt "$requirements_stamp" ] \
    || ! "$venv_python" -c "import fastapi, pytest, weasyprint" >/dev/null 2>&1; then
    log "$YELLOW" "Instalando/actualizando dependencias en backend/.venv..."
    "$venv_python" -m pip install --upgrade pip
    "$venv_python" -m pip install -r "$requirements" -r "$requirements_dev"
    touch "$requirements_stamp"
  fi

  if ! "$venv_python" -c "from weasyprint import HTML" >/dev/null 2>&1; then
    echo -e "${RED}WeasyPrint no puede cargar Pango. Revisa la instalación nativa anterior.${NC}" >&2
    exit 1
  fi

  local frontend_stamp="$FRONTEND_DIR/node_modules/.install.stamp"
  if [ ! -d "$FRONTEND_DIR/node_modules" ] \
    || [ ! -f "$frontend_stamp" ] \
    || [ "$FRONTEND_DIR/package.json" -nt "$frontend_stamp" ] \
    || { [ -f "$FRONTEND_DIR/package-lock.json" ] && [ "$FRONTEND_DIR/package-lock.json" -nt "$frontend_stamp" ]; }; then
    log "$YELLOW" "Instalando dependencias frontend..."
    (cd "$FRONTEND_DIR" && npm install)
    touch "$frontend_stamp"
  fi

  if [ ! -f "$BACKEND_DIR/.env" ]; then
    cp "$BACKEND_DIR/.env.example" "$BACKEND_DIR/.env"
    log "$YELLOW" "Creado backend/.env desde .env.example."
  fi

  ensure_azure_login

  if [ "${SKIP_DB_SETUP:-0}" != "1" ]; then
    log "$YELLOW" "Asegurando esquema de base de datos..."
    (cd "$BACKEND_DIR" && "$venv_python" create_missing_tables.py)
    local alter
    for alter in "$BACKEND_DIR"/alter_*.py; do
      [ -f "$alter" ] || continue
      if grep -Eiq "DROP[[:space:]]+TABLE|TRUNCATE[[:space:]]+TABLE" "$alter"; then
        log "$RED" "$(basename "$alter") contiene DROP/TRUNCATE; se omite por seguridad."
        continue
      fi
      (cd "$BACKEND_DIR" && "$venv_python" "$alter")
    done
  fi

  log "$GREEN" "Entorno listo."
  echo ""
}

if [ "${SKIP_BOOTSTRAP:-0}" != "1" ]; then
  bootstrap
fi

if [ "${BOOTSTRAP_ONLY:-0}" = "1" ]; then
  exit 0
fi

if [ ! -x "$VENV_DIR/bin/uvicorn" ]; then
  echo -e "${RED}No existe backend/.venv o faltan dependencias. Ejecuta ./dev.sh sin SKIP_BOOTSTRAP.${NC}" >&2
  exit 1
fi

start_backend() {
  cd "$BACKEND_DIR"
  exec "$VENV_DIR/bin/uvicorn" app.main:app --reload --port "$BACKEND_PORT"
}

start_frontend() {
  cd "$FRONTEND_DIR"
  exec "$FRONTEND_DIR/node_modules/.bin/vite" --port "$FRONTEND_PORT"
}

echo -e "${CYAN}[backend]${NC} Iniciando FastAPI en :$BACKEND_PORT"
start_backend &
PID_BACK=$!

echo -e "${CYAN}[frontend]${NC} Iniciando Vite en :$FRONTEND_PORT"
start_frontend &
PID_FRONT=$!

echo ""
echo -e "${GREEN}Backend:  http://localhost:$BACKEND_PORT${NC}"
echo -e "${GREEN}Frontend: http://localhost:$FRONTEND_PORT${NC}"
echo -e "${CYAN}Ctrl+C para parar ambos${NC}"
echo ""

wait
