// jsdom in react-scripts 5 predates the Encoding API expected by viem.
import { TextDecoder, TextEncoder } from 'util';

if (!global.TextEncoder) global.TextEncoder = TextEncoder;
if (!global.TextDecoder) global.TextDecoder = TextDecoder;
