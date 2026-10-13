import type { ReactElement } from "react";

/**
 * TMDB's API Terms of Use, section 3, verbatim with the bracketed word substituted.
 *
 * Both notices are component-local rather than shared constants on purpose: they are licence text
 * belonging to this one surface, a paraphrase is a breach rather than a style choice, and nothing
 * else in the app has any business rendering them.
 */
const TMDB_NOTICE =
  "This product uses TMDB and the TMDB APIs but is not endorsed, certified, or otherwise approved by TMDB.";
const TMDB_URL = "https://www.themoviedb.org";
/** TheTVDB's own published sample text, which their terms ask to carry beside a direct link. */
const TVDB_NOTICE = "Metadata provided by TheTVDB. Please consider adding missing information or subscribing.";
const TVDB_URL = "https://thetvdb.com";
const TVDB_LINK_TEXT = "thetvdb.com";
/** TMDB's own mark from their brand page, byte for byte: their terms forbid recolouring or cropping it. */
const TMDB_LOGO_SRC = "/tmdb-logo.svg";
const TMDB_NAME = "TMDB";
const NEW_TAB = "_blank";
/** A new tab that cannot reach back into this one, and carries no referrer to the provider. */
const NEW_TAB_REL = "noopener noreferrer";

/**
 * The metadata providers' attribution, carried on every screen.
 *
 * Both obligations read "displayed to end users viewing metadata" — on the screen where the data
 * appears, not in a settings page — so this mounts once in the sidebar foot, which is the one
 * surface every screen has. That satisfies both the moment a screen starts rendering provider
 * data, and needs no condition that could go stale as more screens start to.
 *
 * The mark sits below this app's own wordmark and at a twelfth of its height, which is what TMDB's
 * terms mean by less prominent, and is served unmodified from `public/` so nothing here recolours
 * or crops it. Both notices are rendered as text: no provider response is interpolated.
 */
export function ProviderAttribution(): ReactElement {
  return (
    <aside className="attribution" aria-label="Metadata attribution">
      <p className="attribution__line">
        <a
          className="attribution__mark"
          href={TMDB_URL}
          target={NEW_TAB}
          rel={NEW_TAB_REL}
          // The link holds the mark and nothing else, so without this both a screen reader and the
          // layout guard would have to name it by its markup.
          aria-label={TMDB_NAME}
        >
          <img className="attribution__logo" src={TMDB_LOGO_SRC} alt={TMDB_NAME} />
        </a>
        {TMDB_NOTICE}
      </p>
      <p className="attribution__line">
        {TVDB_NOTICE}{" "}
        <a className="link" href={TVDB_URL} target={NEW_TAB} rel={NEW_TAB_REL}>
          {TVDB_LINK_TEXT}
        </a>
      </p>
    </aside>
  );
}
