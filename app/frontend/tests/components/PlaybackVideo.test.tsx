import { fireEvent, render, screen } from "@testing-library/react";
import { Provider } from "react-redux";
import { expect, it } from "vitest";

import { PlaybackVideo } from "../../src/components/PlaybackVideo";
import { aPlaybackItemRead } from "../support/aPlaybackItemRead";
import { aPlaybackSnapshot } from "../support/aPlaybackSnapshot";
import { aTestStore } from "../support/aTestStore";

it("retains native accessible controls, same-origin file URL and visible media errors", () => {
  render(<Provider store={aTestStore()}><PlaybackVideo item={aPlaybackItemRead()}
    scope={aPlaybackSnapshot().scope} fileId="file/one" /></Provider>);
  const video = screen.getByLabelText("Video for A Show");
  expect(video).toHaveAttribute("controls");
  expect(video).toHaveAttribute("tabindex", "0");
  expect(video).toHaveAttribute("preload", "none");
  expect(video).toHaveAttribute("src", "/api/playback/file%2Fone/stream");
  fireEvent.error(video);
  expect(screen.getByRole("alert")).toHaveTextContent("This video could not play");
});
