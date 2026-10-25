import type { PanelSection } from '../types.js'

export const SETUP_REQUIRED_TITLE = 'Setup Required'

export const buildSetupRequiredSections = (): PanelSection[] => [
  {
    text: 'Choose a chat model in the Luna dashboard before starting a conversation.'
  },
  {
    rows: [
      ['Setup', 'install the free engine or connect your model provider'],
      ['Models', 'choose a model for this profile'],
      ['System', 'verify the configured chat model']
    ],
    title: 'Actions'
  },
  {
    text: 'Return to Chat after choosing a model. Memory and self-wakes are optional.'
  }
]
