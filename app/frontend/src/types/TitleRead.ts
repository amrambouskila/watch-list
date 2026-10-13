export type MediaType = "movie" | "tv";

export interface TitleRead {
  id: string;
  media_type: MediaType;
  tmdb_id: number | null;
  name: string;
  original_name: string | null;
  first_air_date: string | null;
  last_air_date: string | null;
  runtime_seconds: number | null;
  episode_count: number | null;
  season_count: number | null;
  status: string | null;
  poster_url: string | null;
}
