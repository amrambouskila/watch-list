import type { ReactElement } from "react";

import type { HeroCandidate } from "../types/HeroCandidate";
import { isHttpUrl } from "../utils/isHttpUrl";

interface HeroCandidatesProps {
  readonly candidates: readonly HeroCandidate[];
  readonly disabled: boolean;
  readonly onPick: (choice: number) => void;
}

/** The images on offer, shown against a card-like ground so a transparent mark can be judged. */
export function HeroCandidates({ candidates, disabled, onPick }: HeroCandidatesProps): ReactElement {
  return (
    <ul className="candidates scroll" aria-label="Proposed artwork">
      {candidates.map((candidate, index) => (
        <li className="candidate" key={index}>
          <div className="candidate__frame">
            {isHttpUrl(candidate.url) ? (
              <img className="candidate__image" src={candidate.url} alt={candidate.description} loading="lazy" />
            ) : (
              <span className="candidate__unshowable">{candidate.url}</span>
            )}
          </div>

          <p className="candidate__description">{candidate.description}</p>
          <p className="candidate__licence mono">{candidate.licence}</p>
          <p className="candidate__source">
            {isHttpUrl(candidate.page) ? (
              <a className="link" href={candidate.page} target="_blank" rel="noreferrer noopener">
                {candidate.source_file}
              </a>
            ) : (
              candidate.source_file
            )}
          </p>

          <button
            type="button"
            className="button button--primary candidate__pick"
            disabled={disabled}
            onClick={() => onPick(index)}
          >
            Use this one
          </button>
        </li>
      ))}
    </ul>
  );
}
