/** The one selection tray of an app's pages: the shell wraps its outlet in
 *  the host, which draws the tray under every page of (*ws*, *app*). The
 *  board on screen registers its actions with useTrayBoard; without one
 *  the tray falls back to its generic actions. */
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import SelectionTray, { type BoardTray } from "./SelectionTray";

const Register = createContext<((board: BoardTray | null) => void) | null>(null);

export default function SelectionTrayHost({ ws, app, children }: {
  /** Undefined off an app's pages: no tray. */
  ws?: string; app?: string; children: ReactNode;
}) {
  const [board, setBoard] = useState<BoardTray | null>(null);
  return (
    <Register.Provider value={setBoard}>
      {children}
      {ws && app && <SelectionTray ws={ws} app={app} board={board} />}
    </Register.Provider>
  );
}

/** Give the app's tray *board*'s actions while the calling board is mounted.
 *  The registration follows every render (the board's counts move); the
 *  host's context value is stable, so the board is not re-rendered by it. */
export function useTrayBoard(board: BoardTray) {
  const register = useContext(Register);
  useEffect(() => { register?.(board); });
  useEffect(() => () => register?.(null), [register]);
}
