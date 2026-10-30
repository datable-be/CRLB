You read one stage of the provenance of a work of art, from the Corpus Rubenianum Ludwig Burchard, the catalogue raisonné of Rubens. The provenance is a chronological list of the owners, dealers, institutions and sales of the work; one stage is one item of that list. Return the parts of the stage as JSON.

Rules:

1. Every text value is copied exactly from the stage, character for character, or is null. Never translate, correct, complete, shorten or explain a value. Take nothing from the previous stage: it is only context.
2. `kind` is `auction` if the stage is a sale (`sale`, `his sale`, `her sale`, `sold ... at sale`); `collection` if it names a person, family, dealer or institution that held the work; `other` if it names neither (a remark such as `unknown.`).
3. For a collection: `holder` is the person or institution that held the work, with life dates if they follow the name; `place` is where they held it; `date` is when, as written, with words such as `c.`, `before`, `by`, `until`, `between ... and ...`.
4. For an auction: `place`, `organiser` (the auction house, often in brackets), `date`, `lot`, `consignor` (the seller, only if named in this stage; not `his` or `her`), `buyer` and `price` (the amount only, without the currency) as written. `holder` is null.
5. `note` is a remark of the stage that has no other place, such as the title under which the work was sold: `as circle of Rubens`.
6. `transfer_method` is how the holder got the work, only if the stage says so: bought or purchased is purchase, bequeathed is bequest, given is gift, by descent or inherited is inheritance. `acquired` alone does not say how: then null.
7. `collection_type` only if the holder makes it plain: a museum, a private collection, a dealer, a church, a library. Otherwise null.
8. `currency` only for a price: florins are `florijnen`, pounds are `GBP`, guineas are `guinea`.
9. `uncertain` is true if the stage starts with `?` or says `probably`, `possibly`, `perhaps` or `presumably` about the stage itself.
