import { Fruit } from '../enums';

// We can just redefine the arrays here or read them.
const reelMaps: Record<number, Fruit[]> = {
  0: [
    Fruit.cherry, Fruit.lemon, Fruit.lemon, Fruit.banana, Fruit.banana, Fruit.lemon, Fruit.apple, Fruit.lemon,
    Fruit.cherry, Fruit.lemon, Fruit.lemon, Fruit.banana, Fruit.banana, Fruit.lemon, Fruit.apple, Fruit.lemon,
  ],
  1: [
    Fruit.lemon, Fruit.lemon, Fruit.banana, Fruit.apple, Fruit.cherry, Fruit.lemon, Fruit.lemon, Fruit.apple,
    Fruit.lemon, Fruit.lemon, Fruit.banana, Fruit.apple, Fruit.cherry, Fruit.lemon, Fruit.lemon, Fruit.apple,
  ],
  2: [
    Fruit.lemon, Fruit.apple, Fruit.cherry, Fruit.lemon, Fruit.lemon, Fruit.banana, Fruit.lemon, Fruit.lemon,
    Fruit.lemon, Fruit.apple, Fruit.cherry, Fruit.lemon, Fruit.lemon, Fruit.banana, Fruit.lemon, Fruit.lemon,
  ]
};

export const getSegmentForFruit = (reelIndex: number, fruitStr: string, baseSpins: number = 2): number => {
    // The server returns "CHERRY", "APPLE", "BANANA", "BAR", etc.
    // The frontend enum values: Fruit.cherry ('cherry'), Fruit.apple ('apple'), etc.
    const targetFruit = fruitStr.toLowerCase() as Fruit;
    
    const map = reelMaps[reelIndex];
    // Find all indices that match the target fruit
    const indices = [];
    for (let i = 0; i < map.length; i++) {
        if (map[i] === targetFruit) {
            indices.push(i);
        }
    }
    
    // If not found (e.g. BAR is not in the array? Let's check).
    if (indices.length === 0) {
        // Fallback or handle BAR
        return 16 * baseSpins;
    }
    
    // Pick a random matching index
    const index = indices[Math.floor(Math.random() * indices.length)];
    
    return index + (16 * baseSpins);
}
