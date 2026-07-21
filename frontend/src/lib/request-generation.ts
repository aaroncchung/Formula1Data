export function createRequestGenerationGuard() {
  let generation = 0;

  return {
    begin() {
      generation += 1;
      return generation;
    },
    invalidate() {
      generation += 1;
    },
    isCurrent(token: number) {
      return token === generation;
    }
  };
}
