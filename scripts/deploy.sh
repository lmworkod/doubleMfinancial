#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="${APP_DIR:-/opt/doublemfinancial}"
BRANCH="${DEPLOY_BRANCH:-main}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Ejecuta como root: sudo bash $APP_DIR/scripts/deploy.sh" >&2
  exit 1
fi
if [[ ! -d "$APP_DIR/.git" ]]; then
  echo "No se encuentra el repositorio en $APP_DIR" >&2
  exit 1
fi

cd "$APP_DIR"
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "Hay cambios locales; se cancela para evitar sobrescribirlos." >&2
  exit 1
fi

git fetch --prune origin "$BRANCH"
git checkout "$BRANCH"
git pull --ff-only origin "$BRANCH"

runuser -u doublem -- "$APP_DIR/.venv/bin/pip" install --upgrade "$APP_DIR"
systemctl restart doublem
sleep 3
if ! systemctl is-active --quiet doublem; then
  journalctl -u doublem -n 80 --no-pager
  echo "El servicio no está activo tras el despliegue." >&2
  exit 1
fi
echo "Despliegue completado. Logs: journalctl -u doublem -f"
