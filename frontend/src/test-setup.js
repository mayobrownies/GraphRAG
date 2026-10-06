import { afterEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";

vi.stubEnv("VITE_SUPABASE_URL", "https://x.supabase.co");
vi.stubEnv("VITE_SUPABASE_ANON_KEY", "anon");
afterEach(cleanup);
