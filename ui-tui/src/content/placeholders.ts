import { pick } from '../lib/text.js'

export const PLACEHOLDERS = [
  'What is on your mind?',
  'Help me think this through…',
  'Remind me to…',
  'Plan something with me…',
  'Try "/help" for commands'
]

export const PLACEHOLDER = pick(PLACEHOLDERS)
