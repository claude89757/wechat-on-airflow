import { createAccessKeys } from "./access-keys.mjs";

// Independent resolvers prove cold-cache reachability; no credentials or phone actions.
try {
  for (let i = 0; i < 3; i++) await createAccessKeys().reload();
  console.log(JSON.stringify({ jwksVerified: true, coldFetches: 3 }));
} catch {
  console.log(JSON.stringify({ jwksVerified: false }));
  process.exitCode = 1;
}
