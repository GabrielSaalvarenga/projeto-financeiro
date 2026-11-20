#!/bin/sh
# Mac: embrulha dist/Painel Financeiro.app num .dmg com atalho para Aplicativos (arrastar e soltar).
# Uso (na raiz do projeto, depois do PyInstaller):  sh empacotar/criar_dmg.sh 0.9.0
set -e
VERSAO="${1:?informe a versão, ex.: 0.9.0}"
DIST="${DIST:-dist}"
ARQ="$(uname -m)"   # arm64 (Apple Silicon) ou x86_64 (Intel)
PASTA="$(mktemp -d)"
cp -R "$DIST/Painel Financeiro.app" "$PASTA/"
ln -s /Applications "$PASTA/Aplicativos"
hdiutil create -volname "Painel Financeiro" -srcfolder "$PASTA" -ov -format UDZO \
  "$DIST/PainelFinanceiro-$VERSAO-Mac-$ARQ.dmg"
rm -rf "$PASTA"
echo "Pronto: $DIST/PainelFinanceiro-$VERSAO-Mac-$ARQ.dmg"
