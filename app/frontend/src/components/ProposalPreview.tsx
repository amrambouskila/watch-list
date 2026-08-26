import type { ReactElement } from "react";

import { useAppDispatch } from "../hooks/useAppDispatch";
import { useAppSelector } from "../hooks/useAppSelector";
import { useStandingRows } from "../hooks/useStandingRows";
import { applyProposal, chooseHeroImage, proposalDiscarded } from "../stores/chatSlice";
import { loadCatalog } from "../stores/catalogSlice";
import { selectCategory } from "../stores/uiSlice";
import type { CategorySummary } from "../types/CategorySummary";
import type { Proposal } from "../types/Proposal";
import { categoryIn } from "../utils/categoryIn";
import { isHttpUrl } from "../utils/isHttpUrl";
import { HeroCandidates } from "./HeroCandidates";
import { HeroTarget } from "./HeroTarget";
import { ProposalDiff } from "./ProposalDiff";

interface ProposalPreviewProps {
  readonly proposal: Proposal;
}

function targetOf(proposal: Proposal, target: CategorySummary | null): string {
  if (proposal.body.kind === "create") return `New category · ${proposal.body.category.name}`;
  if (proposal.body.kind === "hero") return `Artwork · ${target?.name ?? proposal.body.category_id}`;
  return `Editing · ${proposal.body.category_id}`;
}

/** Model-supplied text only becomes a link when it is plainly an http(s) address. */
function Source({ url }: { readonly url: string }): ReactElement {
  if (!isHttpUrl(url)) return <>{url}</>;
  return (
    <a className="link" href={url} target="_blank" rel="noreferrer noopener">
      {url}
    </a>
  );
}

/** The proposal and the buttons that decide its fate. Nothing is written until you say so. */
export function ProposalPreview({ proposal }: ProposalPreviewProps): ReactElement {
  const dispatch = useAppDispatch();
  const applying = useAppSelector((state) => state.chat.applying);
  const listing = useAppSelector((state) => state.catalog.listing);
  const standing = useStandingRows(proposal.body.kind === "edit" ? proposal.body.category_id : null);
  const offersArtwork = proposal.body.kind === "hero";
  const target = proposal.body.kind === "hero" ? categoryIn(listing, proposal.body.category_id) : null;

  const approve = async (): Promise<void> => {
    const result = await dispatch(applyProposal(proposal.id));
    if (!applyProposal.fulfilled.match(result)) return;
    await dispatch(loadCatalog());
    dispatch(selectCategory(result.payload.id));
  };

  const pick = async (choice: number): Promise<void> => {
    const result = await dispatch(chooseHeroImage({ proposalId: proposal.id, choice }));
    // The wall is where new artwork actually shows, so a pick refreshes it rather than navigating away.
    if (chooseHeroImage.fulfilled.match(result)) await dispatch(loadCatalog());
  };

  return (
    <section className="proposal" aria-label="Proposed change">
      <header className="proposal__head">
        <span className="eyebrow">{targetOf(proposal, target)}</span>
        <p className="proposal__summary">{proposal.summary}</p>
      </header>

      {proposal.sources.length > 0 && (
        <ul className="proposal__sources">
          {proposal.sources.map((source) => (
            <li key={source}>
              <Source url={source} />
            </li>
          ))}
        </ul>
      )}

      {proposal.body.kind === "hero" ? (
        <>
          <HeroTarget categoryId={proposal.body.category_id} category={target} />
          <HeroCandidates
            candidates={proposal.body.candidates}
            disabled={applying}
            onPick={(choice) => void pick(choice)}
          />
        </>
      ) : (
        <ProposalDiff body={proposal.body} standing={standing} />
      )}

      <div className="proposal__actions">
        <button
          type="button"
          className="button"
          disabled={applying}
          onClick={() => dispatch(proposalDiscarded())}
        >
          {offersArtwork ? "None of these" : "Discard"}
        </button>
        {!offersArtwork && (
          <button type="button" className="button button--primary" disabled={applying} onClick={() => void approve()}>
            {applying ? "Writing…" : "Approve and write"}
          </button>
        )}
      </div>
    </section>
  );
}
