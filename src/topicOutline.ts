export function sourceTarget(ids:string[],knownIds:Set<string>):string|null {
  return ids.find(id=>knownIds.has(id)) ?? null;
}
