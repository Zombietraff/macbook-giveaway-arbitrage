import { Fruit } from '../enums';
import { REEL_MAPS } from '../reelMaps';

const isFruit = (value: string): value is Fruit =>
  Object.values(Fruit).includes(value as Fruit);

export const getSegmentForFruit = (
  reelIndex: number,
  fruitStr: string,
  baseSpins = 2,
): number => {
  if (!isFruit(fruitStr)) {
    throw new Error(`Unknown reel symbol: ${fruitStr}`);
  }

  const map = REEL_MAPS[reelIndex];
  if (!map) {
    throw new Error(`Unknown reel index: ${reelIndex}`);
  }

  const indices = map.reduce<number[]>((matches, fruit, index) => {
    if (fruit === fruitStr) matches.push(index);
    return matches;
  }, []);

  if (indices.length === 0) {
    throw new Error(`Symbol ${fruitStr} is not present on reel ${reelIndex}`);
  }

  const index = indices[Math.floor(Math.random() * indices.length)];
  return index + 16 * baseSpins;
};
