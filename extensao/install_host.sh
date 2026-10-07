#!/bin/bash
# Script para instalar o Native Messaging Host
# Uso: ./install_host.sh <ID_DA_EXTENSAO>
# 
# Para obter o ID:
# 1. Abra seu navegador (Chrome/Brave/Edge) e vá em extensões.
# 2. Ative o "Modo do desenvolvedor".
# 3. Carregue a pasta "extensao" sem compactar.
# 4. Copie o ID gerado e passe para este script.

if [ -z "$1" ]; then
    echo "Erro: Forneça o ID da extensão."
    echo "Uso: $0 <ID_DA_EXTENSAO>"
    exit 1
fi

EXT_ID=$1
HOST_NAME="jornal_eink.native_host"
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
HOST_PATH="$SCRIPT_DIR/host.py"

# Chrome/Chromium/Brave paths
CHROME_DIR="$HOME/.config/google-chrome/NativeMessagingHosts"
CHROMIUM_DIR="$HOME/.config/chromium/NativeMessagingHosts"
BRAVE_DIR="$HOME/.config/BraveSoftware/Brave-Browser/NativeMessagingHosts"
FIREFOX_DIR="$HOME/.mozilla/native-messaging-hosts"

MANIFEST="manifest_host.json"

cat > "$MANIFEST" <<EOF
{
  "name": "$HOST_NAME",
  "description": "Salva links para o Jornal e-Ink",
  "path": "$HOST_PATH",
  "type": "stdio",
  "allowed_origins": [
    "chrome-extension://$EXT_ID/"
  ]
}
EOF

# Install for Chrome-based
for DIR in "$CHROME_DIR" "$CHROMIUM_DIR" "$BRAVE_DIR"; do
    if [ -d "$(dirname "$DIR")" ]; then
        mkdir -p "$DIR"
        cp "$MANIFEST" "$DIR/$HOST_NAME.json"
        echo "Instalado em: $DIR/$HOST_NAME.json"
    fi
done

# Install for Firefox (requires allowed_extensions)
FIREFOX_MANIFEST="manifest_host_firefox.json"
cat > "$FIREFOX_MANIFEST" <<EOF
{
  "name": "$HOST_NAME",
  "description": "Salva links para o Jornal e-Ink",
  "path": "$HOST_PATH",
  "type": "stdio",
  "allowed_extensions": [
    "jornaleink@ykosfeld"
  ]
}
EOF

if [ -d "$(dirname "$FIREFOX_DIR")" ]; then
    mkdir -p "$FIREFOX_DIR"
    cp "$FIREFOX_MANIFEST" "$FIREFOX_DIR/$HOST_NAME.json"
    echo "Instalado em: $FIREFOX_DIR/$HOST_NAME.json"
fi

rm "$MANIFEST" "$FIREFOX_MANIFEST"

echo "Instalação do Native Messaging concluída!"
