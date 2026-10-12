#!/usr/bin/env bash
set -e

INSTALL_DIR="${HOME}/.local/bin"
mkdir -p "${INSTALL_DIR}"

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ ! -f "${REPO_DIR}/agy-chats" ] || [ ! -f "${REPO_DIR}/agy-fork" ]; then
  echo "Error: Cannot find agy-chats and agy-fork scripts at ${REPO_DIR}"
  exit 1
fi

chmod +x "${REPO_DIR}/agy-chats" "${REPO_DIR}/agy-fork"

# Link or copy to ~/.local/bin
ln -sf "${REPO_DIR}/agy-chats" "${INSTALL_DIR}/agy-chats"
ln -sf "${REPO_DIR}/agy-chats" "${INSTALL_DIR}/agy-history"
ln -sf "${REPO_DIR}/agy-fork"  "${INSTALL_DIR}/agy-fork"

echo "✓ Successfully installed unified suite into ${INSTALL_DIR}:"
echo "  - ${INSTALL_DIR}/agy-chats"
echo "  - ${INSTALL_DIR}/agy-fork"
echo "  - ${INSTALL_DIR}/agy-history"

# Check PATH
case ":$PATH:" in
  *":${INSTALL_DIR}:"*) ;;
  *)
    echo ""
    echo "Note: ${INSTALL_DIR} is not in your PATH."
    echo "Add this to your shell rc (~/.bashrc or ~/.zshrc):"
    echo '  export PATH="$HOME/.local/bin:$PATH"'
    ;;
esac
