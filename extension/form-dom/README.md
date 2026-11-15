# Self-contained form executor

The fragments preserve one private closure. They are assembled into `../form-dom.js`
without runtime imports or evaluation so Chromium can serialize the function into an
isolated world. Edit these source fragments, run `pnpm -C extension dom:generate`,
and commit the generated artifact. Builds and tests reject generated drift.

The five sections separate field helpers, observation state, inspection, snapshot
verification and filling. Their order is explicit in the generator. Website text is
data; the private DOM references and authority checks stay inside the closure.
