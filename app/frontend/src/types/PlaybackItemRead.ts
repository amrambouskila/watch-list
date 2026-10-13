import type { Availability } from "./Availability";

export interface PlaybackItemRead {
  id: string;
  entry_id: string;
  episode_id: string | null;
  movie_title_id: string | null;
  position_in_entry: number;
  absolute_position: number;
  availability: Availability;
  jellyfin_item_id: string | null;
  order_type: string | null;
  order_label: string;
  covers_range: boolean;
}
