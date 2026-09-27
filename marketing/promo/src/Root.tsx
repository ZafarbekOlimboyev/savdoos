import React from 'react';
import { Composition } from 'remotion';

import { PROOF_FRAMES, ProofOfStyle } from './compositions/ProofOfStyle';
import { FPS, H, W } from './theme';

export const RemotionRoot: React.FC = () => (
  <>
    <Composition
      id="ProofOfStyle"
      component={ProofOfStyle}
      durationInFrames={PROOF_FRAMES}
      fps={FPS}
      width={W}
      height={H}
      defaultProps={{ lang: 'uz' as const }}
    />
  </>
);
