#!/usr/bin/env bash
# Abre o Painel Financeiro (Linux e Mac). Ver README, "Jeito mais fácil".
cd "$(dirname "$0")" || exit 1

PYTHON=""
for c in python3.12 python3.13 python3.11 python3.10 python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
    PYTHON="$c"; break
  fi
done

if [ -z "$PYTHON" ]; then
  echo
  echo "[ERRO] Não encontrei o Python (precisa da versão 3.10 ou mais nova; o recomendado é a 3.12)."
  case "$(uname -s)" in
    Darwin) echo "Instale em https://www.python.org/downloads/ e rode este arquivo de novo." ;;
    *)      echo "Instale com o gerenciador do seu sistema, por exemplo: sudo apt install python3 python3-venv python3-pip" ;;
  esac
  read -r -p "Aperte Enter para fechar…" _
  exit 1
fi

"$PYTHON" iniciar.py
status=$?
if [ $status -ne 0 ]; then read -r -p "Aperte Enter para fechar…" _; fi
exit $status
