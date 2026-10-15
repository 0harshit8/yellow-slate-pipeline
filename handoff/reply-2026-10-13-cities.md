# Reply to Yellow Slate tech team — 13 Oct 2026

Draft. Review before sending.

---

Subject: Re: The 29 held cities — our answer is option 3, don't move them

Thanks for the 99, and thanks for laying the trade-off out this clearly.

**Our answer is option 3: leave all 29 as areas. Do not move them on our account.**

We are not blocked by them. You should not take ranking risk on 140 live schools to unblock
something that is already unblocked.

## Why we don't need the move

Your Oct 11 update is what changed this. Area is optional on `GET /schools/search`, and your
reply tells us each school's area. So we never have to send "Thane" anywhere:

- We search `name=... &city=Mumbai`, and your answer comes back with `area: Thane`. We file
  the school under the area *you* returned, never the one we guessed.
- `POST /blogs` keeps the slug we send rather than regenerating it, so our blog URLs don't
  depend on whether Thane is a city or an area. A "schools in Thane" post lives at the same
  address either way.
- The keyword just carries `city = Mumbai, area = Thane` instead of `city = Thane`. That is a
  one-column change in our sheet, not a code change.

So the area route costs us close to nothing, and the move costs you a migration, 140 school
redirects, the old area-page redirects, and a few weeks of ranking wobble. That is not a
trade we want you to make for us.

With the 99 you added, we are at 271 of 300 cities running as cities and the remaining 29
running through the area route. Effectively nothing on our list is blocked any more.

## If you move them anyway — three conditions

The SEO case for Thane being a city of its own is a real one, and it is yours to judge, not
ours. If you decide to move on that basis, your option 2 is the right shape: the 9 big ones,
tested first, leave the rest. Three things we'd need, and the first one is a genuine break.

**1. Do not name the child area after the city.** This is the important one.

You said a city with no areas has no listing pages, so the area moves with the schools. If
that means city `Thane` ends up containing area `Thane`, it breaks our create path.

An area with the same name as its own city is your catch-all, and no school is filed under
it. We measured that in Lucknow in October: a keyword resolved to `city = Lucknow, area =
Lucknow`, every search against it missed, and we created a duplicate of a school you already
had. Our code now refuses any area equal to its city, by name, and skips the school. So on
day one of city `Thane` / area `Thane`, every Thane school we need to *create* would be
skipped on our side — and a brand-new city is mostly schools you don't have yet.

Please give the moved cities real localities instead — Ghodbunder Road, Vartak Nagar,
Dombivli, Kopar Khairane, whatever the schools actually sit in. If a single bucket is
unavoidable, name it something that isn't the city and tell us the string.

**2. Don't let a place exist both ways.** Every NCR town we tested — Noida, Greater Noida,
Ghaziabad, Faridabad, Gurugram — is already both a city of its own *and* an area under Delhi.
"Schools in Noida" resolves two different ways and returns two different sets of schools. If
the old `mumbai/thane` area survives the move alongside city `Thane`, we inherit that same
split for 9 more places. Pick one and retire the other.

While we're on it: we treat the NCR towns as cities in their own right. Tell us if that's
wrong — and if you ever intend to clean that duplication up, we'd like to know before it
happens.

**3. Tell us the exact spelling and the go-live date, and do one first.** Your CMS matches a
city on the exact string, and an unknown city is a hard `404 UNKNOWN_CITY` for us. So
"Pimpri Chinchwad" vs "Pimpri-Chinchwad" vs "Pimpri Chinchwad Municipal Corporation" are
three different answers, and only you know which one you created. One city moved first,
with the spelling, lets us re-run our city check and confirm the whole path before the other
eight follow.

## The one thing we'd gain

Worth saying, so you can weigh it: a moved city would narrow our school-name searches. Your
`candidates` list looks capped at 5, so `name=Delhi Public School&city=Mumbai` can hide a
Thane school behind four Mumbai ones. Scoped to `city=Thane`, that stops being a risk. It is
a real improvement, but a small one against the ranking exposure — and a total count or
paging on `candidates` would fix it for every city at once, not just these 9.

## One question that could change our answer

Does the `city` and `area` we send to `POST /blogs` affect where the post appears on the
site? If a Thane post filed under `city = Mumbai` lands on a Mumbai blog listing and never a
Thane one, the area route is worse than we think and we'd want to revisit. If those fields
are filing metadata and the slug drives everything, option 3 stands.

## Still open from the 11th

Not urgent against this, but the first one still blocks our write stage:

- When `POST /blogs` gets an existing slug and returns `created: false`, is the content
  updated or left alone? We can't test it from outside, and it decides whether a retried
  batch can clobber a finished blog.
- `GET /blogs/{id}`, so we can read back what we wrote.
- The five `VERIFY` rows from our create-path test (school `23205`, drafts `3081` and `3082`,
  3 pngs) still need deleting on your side.

Thanks again.
