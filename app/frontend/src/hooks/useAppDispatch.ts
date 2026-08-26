import { useDispatch } from "react-redux";

import type { AppDispatch } from "../stores/store";

export const useAppDispatch: () => AppDispatch = useDispatch;
