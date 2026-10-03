/** How a report's media panels address an artifact: the artifact download
 *  live, an inlined data URI in an exported report. */
import { createContext, useContext } from "react";
import { artifactUrl } from "../api";

export type MediaUrl = (ws: string, app: string, verstr: string, path: string) => string;

export const MediaUrlContext = createContext<MediaUrl>(artifactUrl);

export const useMediaUrl = () => useContext(MediaUrlContext);
