/** Rows per leaderboard request. Pages are bounded so a workspace with tens of
 *  thousands of runs never ships them all in one response (the server caps `limit` at 1000 anyway). */
export const PAGE_SIZE = 200;
