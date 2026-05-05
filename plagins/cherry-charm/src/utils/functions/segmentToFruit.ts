import { Fruit } from '../enums';
import { REEL_MAPS } from '../reelMaps';

const segmentToFruit = (reel: number, segment: number): Fruit | undefined => {
  const normalizedSegment = segment % 16;
  return REEL_MAPS[reel]?.[normalizedSegment];
};

export default segmentToFruit;
