import { render, screen } from '@testing-library/react';
import App from './App';

test('renders playlist converter heading', () => {
  render(<App />);
  const heading = screen.getByRole('heading', { name: /playlist converter/i });
  expect(heading).toBeInTheDocument();
});
