#!/usr/bin/env bash
set -e

INSTALL_DIR="${HOME}/.local/bin"
mkdir -p "${INSTALL_DIR}"

SCRIPT_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/agy-chats"

if [ ! -f "${SCRIPT_SRC}" ]; then
  echo "Error: Cannot find agy-chats script at ${SCRIPT_SRC}"
  exit 1
fi

chmod +x "${SCRIPT_SRC}"

# Link or copy to ~/.local/bin
ln -sf "${SCRIPT_SRC}" "${INSTALL_DIR}/agy-chats"
ln -sf "${SCRIPT_SRC}" "${INSTALL_DIR}/agy-history"

echo "✓ Successfully installed:"
echo "  - ${INSTALL_DIR}/agy-chats"
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

# Optional dependency check
if ! command -v fzf &>/dev/null; then
  echo ""
  echo "Tip: Install 'fzf' for interactive fuzzy searching with live preview."
  echo "     (Falls back to native curses TUI if fzf is not installed)"
fi
