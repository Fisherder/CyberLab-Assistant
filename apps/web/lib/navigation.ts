export function teacherChallengeBankHref(createdItemId?: string): string {
  if (!createdItemId) return "/teacher/challenge-bank";
  return `/teacher/challenge-bank?created=${encodeURIComponent(createdItemId)}`;
}
