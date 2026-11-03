// The folder the dashboard is served from, from <base href> in index.html:
// "/" on the van, e.g. "/kombi/" for a remote dashboard in a subfolder.
export const BASE_PATH: string = (() => {
  try {
    const path = new URL(".", document.baseURI).pathname;
    return path.endsWith("/") ? path : `${path}/`;
  } catch {
    return "/";
  }
})();

/** For react-router: "" at the root, "/kombi" in a subfolder. */
export const ROUTER_BASENAME = BASE_PATH.replace(/\/$/, "");
