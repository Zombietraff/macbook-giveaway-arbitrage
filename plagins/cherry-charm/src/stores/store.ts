import { create } from 'zustand';
import { subscribeWithSelector } from 'zustand/middleware';
import { Fruit } from '../utils/enums';
import { LanguageCode } from '../i18n';

const STAKE_TIERS = [1, 2, 3, 4, 5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 200, 500];
const MIN_REMAINING_TICKETS = 1;

type State = {
  isMobile: boolean;
  setIsMobile: (value: boolean) => void;
  modal: boolean;
  setModal: (isOpen: boolean) => void;
  languageCode: LanguageCode;
  setLanguageCode: (languageCode: LanguageCode) => void;
  isUserLoaded: boolean;
  setUserLoaded: (isLoaded: boolean) => void;
  disclaimerAccepted: boolean;
  setDisclaimerAccepted: (isAccepted: boolean) => void;
  coins: number;
  setCoins: (amount: number) => void;
  updateCoins: (amount: number) => void;
  fruit0: Fruit | '';
  setFruit0: (fr: Fruit | '') => void;
  fruit1: Fruit | '';
  setFruit1: (fr: Fruit | '') => void;
  fruit2: Fruit | '';
  setFruit2: (fr: Fruit | '') => void;
  showBars: boolean;
  toggleBars: () => void;
  bet: number;
  appliedBet: number;
  updateBet: (direction: number) => void;
  validateBet: () => void;
  win: number;
  serverWinAmount: number;
  setServerWinAmount: (amount: number) => void;
  setWin: (amount: number) => void;
  spins: number;
  addSpin: () => void;
  startTime: number;
  endTime: number;
  phase: 'idle' | 'spinning';
  start: (betAtLaunch: number) => void;
  end: () => void;
  firstTime: boolean;
  setFirstTime: (isFirstTime: boolean) => void;
};

const useGame = create<State>()(
  subscribeWithSelector((set) => ({
    isMobile: window.innerWidth < 768,
    setIsMobile: (value: boolean) => set(() => ({ isMobile: value })),
    modal: false,
    setModal: (isOpen: boolean) => set({ modal: isOpen }),
    languageCode: 'ru',
    setLanguageCode: (languageCode: LanguageCode) => set({ languageCode }),
    isUserLoaded: false,
    setUserLoaded: (isLoaded: boolean) => set({ isUserLoaded: isLoaded }),
    disclaimerAccepted: false,
    setDisclaimerAccepted: (isAccepted: boolean) =>
      set({ disclaimerAccepted: isAccepted }),

    /**
     * Coins: Just updates the value.
     * Snap-down logic removed from here to prevent bet resetting mid-spin.
     */
    coins: 1000,
    setCoins: (amount: number) => set(() => ({ coins: amount })),
    updateCoins: (amount: number) => {
      set((state) => ({ coins: state.coins + amount }));
    },

    fruit0: '',
    setFruit0: (fr: Fruit | '') => set({ fruit0: fr }),
    fruit1: '',
    setFruit1: (fr: Fruit | '') => set({ fruit1: fr }),
    fruit2: '',
    setFruit2: (fr: Fruit | '') => set({ fruit2: fr }),
    showBars: false,
    toggleBars: () => set((state) => ({ showBars: !state.showBars })),

    /**
     * Bet Logic
     */
    bet: 1,
    appliedBet: 1,
    updateBet: (direction: number) => {
      set((state) => {
        const currentIndex = STAKE_TIERS.indexOf(state.bet);
        const nextIndex = currentIndex + direction;
        if (nextIndex < 0 || nextIndex >= STAKE_TIERS.length) return {};
        const newBet = STAKE_TIERS[nextIndex];
        const maxPlayableBet = state.coins - MIN_REMAINING_TICKETS;
        if (newBet > maxPlayableBet && direction > 0) return {};
        return { bet: newBet };
      });
    },

    /**
     * Validate Bet: Called only when the round ends to check
     * if the player can still afford their current bet tier.
     */
    validateBet: () => {
      set((state) => {
        const maxPlayableBet = state.coins - MIN_REMAINING_TICKETS;
        if (state.bet > maxPlayableBet) {
          const affordableTiers = STAKE_TIERS.filter((t) => t <= maxPlayableBet);
          const currentBet =
            affordableTiers.length > 0
              ? affordableTiers[affordableTiers.length - 1]
              : STAKE_TIERS[0];
          return { bet: currentBet };
        }
        return {};
      });
    },

    win: 0,
    serverWinAmount: 0,
    setServerWinAmount: (amount: number) => set({ serverWinAmount: amount }),
    setWin: (amount: number) => set({ win: amount }),
    spins: 0,
    addSpin: () => set((state) => ({ spins: state.spins + 1 })),
    startTime: 0,
    endTime: 0,
    phase: 'idle',
    start: (betAtLaunch: number) => {
      set((state) => {
        if (state.phase === 'idle') {
          return {
            phase: 'spinning',
            startTime: Date.now(),
            appliedBet: betAtLaunch,
          };
        }
        return {};
      });
    },
    end: () => {
      set((state) => {
        if (state.phase === 'spinning') {
          return { phase: 'idle', endTime: Date.now() };
        }
        return {};
      });
    },
    firstTime: true,
    setFirstTime: (isFirstTime: boolean) => set({ firstTime: isFirstTime }),
  })),
);

export default useGame;
